<?php

namespace App\Filament\Resources\BlockedUserResource\Pages;

use App\Filament\Resources\BlockedUserResource;
use Filament\Actions;
use Filament\Resources\Pages\ListRecords;

class ListBlockedUsers extends ListRecords
{
    protected static string $resource = BlockedUserResource::class;

    protected function getHeaderActions(): array
    {
        return [
            Actions\CreateAction::make(),
        ];
    }
}
