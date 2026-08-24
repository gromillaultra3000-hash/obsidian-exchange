<?php

namespace App\Filament\Resources;

use App\Filament\Resources\BlockedUserResource\Pages;
use App\Models\BlockedUser;
use Filament\Forms;
use Filament\Forms\Form;
use Filament\Resources\Resource;
use Filament\Tables;
use Filament\Tables\Table;

class BlockedUserResource extends Resource
{
    protected static ?string $model = BlockedUser::class;

    protected static ?string $navigationIcon = 'heroicon-o-no-symbol';

    protected static ?string $navigationLabel = 'Блокировки';

    protected static ?string $modelLabel = 'блокировка';

    protected static ?string $pluralModelLabel = 'блокировки';

    public static function form(Form $form): Form
    {
        return $form
            ->schema([
                Forms\Components\TextInput::make('user_id')
                    ->label('User ID')
                    ->numeric()
                    ->minValue(1)
                    ->required()
                    ->disabledOn('edit'),
                Forms\Components\TextInput::make('reason')
                    ->label('Причина')
                    ->default('admin block')
                    ->maxLength(500)
                    ->columnSpanFull(),
            ]);
    }

    public static function table(Table $table): Table
    {
        return $table
            ->defaultSort('blocked_at', 'desc')
            ->columns([
                Tables\Columns\TextColumn::make('user_id')
                    ->label('User ID')
                    ->searchable()
                    ->sortable(),
                Tables\Columns\TextColumn::make('reason')
                    ->label('Причина'),
                Tables\Columns\TextColumn::make('blocked_at')
                    ->label('Когда')
                    ->dateTime('d.m.Y H:i')
                    ->sortable(),
            ])
            ->filters([])
            ->actions([
                Tables\Actions\DeleteAction::make()
                    ->label('Разблокировать'),
            ])
            ->bulkActions([
                Tables\Actions\BulkActionGroup::make([
                    Tables\Actions\DeleteBulkAction::make()
                        ->label('Разблокировать'),
                ]),
            ]);
    }

    public static function getPages(): array
    {
        return [
            'index' => Pages\ListBlockedUsers::route('/'),
            'create' => Pages\CreateBlockedUser::route('/create'),
        ];
    }

    public static function canEdit($record): bool
    {
        return false;
    }
}
